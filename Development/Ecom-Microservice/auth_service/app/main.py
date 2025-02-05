from fastapi import FastAPI, Depends, HTTPException, Request, status, Form, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app import models, schemas, database, auth
from datetime import timedelta
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
import logging





# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI()


ACCESS_TOKEN_EXPIRE_MINUTES = 30  # Set the desired number of minutes here

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to restrict origins as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates setup
templates = Jinja2Templates(directory="templates")

# Populate permissions in the database at startup
with database.SessionLocal() as db:
    database.create_permissions(db) 

# Ensure the database tables are created
models.Base.metadata.create_all(bind=database.engine)

@app.get("/auth/register")
async def get_register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

# Updated /auth/register route to include user roles
@app.post("/auth/register", response_model=schemas.UserOut)
def register_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: schemas.RoleEnum = Form(default=schemas.RoleEnum.USER),
    db: Session = Depends(database.get_db)
):
    try:
        logger.debug(f"Attempting to register user: {username}, {email}, role: {role}")
        
        db_user = db.query(models.User).filter(models.User.email == email).first()
        if db_user:
            logger.warning(f"Email already registered: {email}")
            raise HTTPException(status_code=400, detail="Email already registered")
        
        hashed_password = auth.get_password_hash(password)
        new_user = models.User(username=username, email=email, hashed_password=hashed_password, role=role)
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        # Assign permissions based on the user's role
        auth.assign_permissions(new_user, db)

        # Prepare the response with permissions
        permissions_list = [user_permission.permission.name for user_permission in new_user.permissions]
        logger.info(f"Successfully registered user: {username}, {email}, role: {role}")

        return {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "role": new_user.role,
            "permissions": permissions_list
        }
    except Exception as e:
        logger.error(f"Error registering user: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")



@app.post("/auth/login")
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(database.get_db)
):
    # Authenticate the user
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create the access token with expiration and role included
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.email, "role": user.role},  # Include user role in the token
        expires_delta=access_token_expires
    )
    
    # Set the user_id as an HttpOnly cookie (to prevent client-side access)
    response.set_cookie(
        key="user_id",
        value=str(user.id),
        httponly=True,  # HttpOnly flag makes it inaccessible via JavaScript
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Set cookie expiration
        secure=True,  # Use secure flag in production (HTTPS)
        samesite="Lax"  # Adjust based on your security needs (Lax, Strict, or None)
    )

    # Explicitly return the role in the response, along with the access token
    return {"access_token": access_token, "token_type": "bearer", "role": user.role, "username": user.username, "email": user.email}


@app.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="user_id")
    return {"message": "Logout successful"}

@app.get("/user/{user_id}", response_model=schemas.UserOut)
async def get_user_profile(user_id: int):
    db = database.get_db()
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/users/me", response_model=schemas.UserOut)
async def read_users_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


